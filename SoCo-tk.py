#!/usr/bin/env python

import tkinter as tk
import logging, traceback
logging.basicConfig(format='%(asctime)s %(levelname)10s: %(message)s', level = logging.INFO)
from tkinter import messagebox
import urllib
import base64
import platform, os
from io import BytesIO
import requests

import sqlite3 as sql
import contextlib as clib

try:
    import soco
    import soco.core
    # from soco.core import Soco as SocoClass
except:
    logging.warning('Could not import soco, trying from local file')
    try:
        import sys
        sys.path.append('./SoCo')
        import soco
    except:
        logging.error('Could not find SoCo library')
        soco = None
        messagebox.showerror(title = 'SoCo',
                               message = 'Could not find SoCo library, make sure you have installed SoCo!',
                               parent = None)
        exit()

try:
    from PIL import Image, ImageTk
except:
    logging.error('Could not import PIL')
    logging.error(traceback.format_exc())
    ImageTk = None
    Image = None

USER_DATA = None

if platform.system() == 'Windows':
    USER_DATA = os.path.join(os.getenv('APPDATA'), 'SoCo-Tk')
elif platform.system() == 'Linux':
    USER_DATA = '%(sep)shome%(sep)s%(name)s%(sep)s.config%(sep)sSoCo-Tk%(sep)s' % {
    'sep' : os.sep,
    'name': os.environ['LOGNAME']
    }

"""
Monkey Patching!
"""
def better_display(self):
        return "{} (\"{}\")".format(self.player_name, self.ip_address).title()
soco.core.SoCo.__str__=better_display


class SonosList(tk.PanedWindow):

    def __init__(self, parent):
        self.__parent = parent
        tk.PanedWindow.__init__(self, parent, sashrelief = tk.RAISED)

        self.__parent.protocol('WM_DELETE_WINDOW', self._clean_exit)
        
        self.grid(row = 0,
                  column = 0,
                  ipadx = 5,
                  ipady = 5,
                  sticky = 'news')

        self.__list_content = []
        self.__queue_content = []

        self._control_buttons = {}
        self._info_widget = {}

        self.__last_selected = None
        self.__last_image = None
        self.__current_speaker = None
        self._connection = None

        self.empty_info = '-'
        self.label_queue = '{} - {}'

        self._create_widgets()
        self._create_menu()

        parent.rowconfigure(0, weight = 1)
        parent.columnconfigure(0, weight = 1)
        self.rowconfigure(0, weight = 1)
        self.columnconfigure(0, weight = 1)

        self._load_settings()
        self._update_buttons()

    def destroy(self):
        try:
            del self.__list_content[:]
            del self.__queue_content[:]
            if self.__current_speaker:
                del self.__current_speaker
                self.__current_speaker = None

            if self._connection:
                logging.info('Closing database connection')
                self._connection.close()
                self._connection = None
        except:
            logging.error('Error while destroying')
            logging.error(traceback.format_exc())
        
    def __del__(self):
        self.destroy()

    def scan_speakers(self):
        speakers = list(soco.discover())
        logging.debug('Found %d speaker(s)', len(speakers))
        [s.get_speaker_info() for s in speakers]
        self.__add_speakers(speakers)

    def _clean_exit(self):
        try:
            geometry = self.__parent.geometry()
            if geometry:
                logging.debug('Storing geometry: "%s"', geometry)
                self.__set_config('window_geometry', geometry)

            listOfPanes = self.panes()
            sashes = []
            for index in range(len(listOfPanes) - 1):
                x, y = self.sash_coord(index)
                sashes.append(':'.join((str(index),
                                        str(x),
                                        str(y))))

            finalSashValue = ','.join(sashes)
            logging.debug('Storing sashes: "%s"', finalSashValue)
            self.__set_config('sash_coordinates', finalSashValue)
                
        except:
            logging.error('Error making clean exit')
            logging.error(traceback.format_exc())
        finally:
            self.destroy()
            self.__parent.quit()
            

    def __add_speakers(self, speakers):
        logging.debug('Deleting all items from list')
        self._listbox.delete(0, tk.END)
        del self.__list_content[:]
        self.__list_content = []

        if not speakers:
            logging.debug('No speakers to add, returning')
            return
        
        logging.debug('Inserting new items (%d)', len(speakers))
        for speaker in speakers:
            self.__list_content.append(speaker)
            self._listbox.insert(tk.END, speaker)
        
    def _create_widgets(self):
        logging.debug('Creating widgets')
        # Left frame
        self._left = tk.Frame(self)
        self.add(self._left)
                          
        # Center frame
        self._center = tk.Frame(self)
        self.add(self._center)

        # Right frame
        self._right = tk.Frame(self)
        self.add(self._right)

        # Create Sonos list
        self._listbox = tk.Listbox(self._left,
                                   selectmode = tk.EXTENDED)

        self._listbox.bind('<<ListboxSelect>>', self._listbox_selected)
        
        self._listbox.grid(row = 0,
                           column = 0,
                           columnspan = 5,
                           padx = 5,
                           pady = 5,
                           sticky = 'news')


        # Create queue list
        scrollbar = tk.Scrollbar(self._right)
        self._queuebox = tk.Listbox(self._right,
                                    selectmode = tk.EXTENDED)

        scrollbar.config(command = self._queuebox.yview)
        self._queuebox.config(yscrollcommand = scrollbar.set)
        self._queuebox.bind('<Double-Button-1>', self._play_selected_queue_item)
        
        scrollbar.grid(row = 0,
                       column = 1,
                       pady = 5,
                       sticky = 'ns')
        
        self._queuebox.grid(row = 0,
                            column = 0,
                            padx = 5,
                            pady = 5,
                            sticky = 'news')

        self._create_buttons()
                          
        self._left.rowconfigure(0, weight = 1)
        self._left.columnconfigure(0, weight = 1)

        self._center.rowconfigure(0, weight = 1)
        self._center.columnconfigure(0, weight = 1)

        self._right.rowconfigure(0, weight = 1)
        self._right.columnconfigure(0, weight = 1)

        self._info = tk.Frame(self._center)
        self._info.grid(row = 0,
                        column = 0,
                        padx = 5,
                        pady = 5,
                        sticky = 'news')

        self._info.rowconfigure(9, weight = 1)
        self._info.columnconfigure(1, weight = 1)

        self._create_info_widgets()

    def _create_info_widgets(self):
        infoIndex = 0

        ###################################
        # Title
        ###################################
        label = tk.Label(self._info, text = 'Title:')
        label.grid(row = infoIndex,
                   column = 0,
                   sticky = 'w')
        
        self._info_widget['title'] = tk.Label(self._info,
                                             text = self.empty_info,
                                             anchor = 'w')
        
        self._info_widget['title'].grid(row = infoIndex,
                                       column = 1,
                                       padx = 5,
                                       pady = 5,
                                       sticky = 'we')
        infoIndex += 1

        ###################################
        # Artist
        ###################################
        label = tk.Label(self._info, text = 'Artist:')
        label.grid(row = infoIndex,
                   column = 0,
                   sticky = 'w')
        
        self._info_widget['artist'] = tk.Label(self._info,
                                             text = self.empty_info,
                                             anchor = 'w')
        
        self._info_widget['artist'].grid(row = infoIndex,
                                        column = 1,
                                        padx = 5,
                                        pady = 5,
                                        sticky = 'we')
        infoIndex += 1

        ###################################
        # Album
        ###################################
        label = tk.Label(self._info, text = 'Album:')
        label.grid(row = infoIndex,
                   column = 0,
                   sticky = 'w')
        
        self._info_widget['album'] = tk.Label(self._info,
                                             text = self.empty_info,
                                             anchor = 'w')
        
        self._info_widget['album'].grid(row = infoIndex,
                                       column = 1,
                                       padx = 5,
                                       pady = 5,
                                       sticky = 'we')
        infoIndex += 1

        ###################################
        # Volume
        ###################################
        label = tk.Label(self._info, text = 'Volume:')
        label.grid(row = infoIndex,
                   column = 0,
                   sticky = 'w')
        
        self._info_widget['volume'] = tk.Scale(self._info,
                                              from_ = 0,
                                              to = 100,
                                              tickinterval = 10,
                                              orient = tk.HORIZONTAL)
        
        self._info_widget['volume'].grid(row = infoIndex,
                                        column = 1,
                                        padx = 5,
                                        pady = 5,
                                        sticky = 'we')

        self._info_widget['volume'].bind('<ButtonRelease-1>', self._volume_changed_event)
        infoIndex += 1

        ###################################
        # Album art
        ###################################
        self._info_widget['album_art'] = tk.Label(self._info,
                                                 image = tk.PhotoImage(),
                                                 width = 150,
                                                 height = 150)
        
        self._info_widget['album_art'].grid(row = infoIndex,
                                           column = 1,
                                           padx = 5,
                                           pady = 5,
                                           sticky = 'nw')

    def __get_selected_speaker(self):
        if self.__current_speaker:
            return self.__current_speaker
        
        widget = self._listbox

        selection = widget.curselection()
        if not selection:
            return None

        index = int(selection[0])
        
        assert len(self.__list_content) > index
        speaker = self.__list_content[index]

        return speaker

    def __get_selected_queue_item(self):
        widget = self._queuebox

        selection = widget.curselection()
        if not selection:
            return None, None

        index = int(selection[0])

        assert len(self.__queue_content) > index
        track = self.__queue_content[index]

        return track, index
        
    def _volume_changed_event(self, evt):
        if not self.__current_speaker:
            logging.warning('No speaker selected')
            return
        
        speaker = self.__current_speaker
        volume = self._info_widget['volume'].get()

        logging.debug('Changing volume to: %d', volume)
        speaker.volume(volume)

    def __clear(self, typeName):
        if typeName == 'queue':
            logging.debug('Deleting old items')
            self._queuebox.delete(0, tk.END)
            del self.__queue_content[:]
            self.__queue_content = []
        elif typeName == 'album_art':
            self._info_widget[typeName].config(image = None)
            if self.__last_image:
                del self.__last_image
                self.__last_image = None
        
    def _listbox_selected(self, evt):
        # Note here that Tkinter passes an event object to onselect()
        widget = evt.widget

        selection = widget.curselection()
        if not selection:
            # self.show_speaker_info(None)
            self._update_buttons()
            self.__set_config('last_selected', None)
            return

        index = int(selection[0])
        
        assert len(self.__list_content) > index
        speaker = self.__list_content[index]

        if speaker == self.__current_speaker:
            logging.info('Speaker already selected, skipping')
            return
        
        self.show_speaker_info(speaker)
        self._update_buttons()
                
        logging.debug('Zoneplayer: "%s"', speaker)

        logging.debug('Storing last_selected: %s' % speaker.speaker_info['uid'])
        self.__set_config('last_selected', speaker.speaker_info['uid'])
        

    def show_speaker_info(self, speaker, refresh_queue=None):
        refresh_queue = True
        if speaker is not None and (
            not isinstance(speaker, soco.SoCo)):
            raise TypeError('Unsupported type: %s', type(speaker))

        self.__current_speaker = speaker
        
        newState = tk.ACTIVE if speaker is not None else tk.DISABLED
        self._info_widget['volume'].config(state = newState)
        
        if speaker is None:
            for info in self._info_widget.keys():
                if info == 'volume':
                    self._info_widget[info].set(0)
                    continue
                elif info == 'album_art':
                    self.__clear(info)
                    continue
                
                self._info_widget[info].config(text=self.empty_info)
            logging.info("Removed track info")
            return

        #######################
        # Load speaker info
        #######################
        playingTrack = None
        try:
            logging.info('Receive speaker info from: "%s"' % speaker)
            track = speaker.get_current_track_info()
            playingTrack = track['uri']

            track['volume'] = speaker.volume
            
            self.__clear('album_art')
            for info, value in track.items():
                # import pdb; pdb.set_trace()
                if info == 'album_art':
                    self.__set_album_art(value, track_uri = playingTrack)
                    continue
                elif info == 'volume':
                    self._info_widget[info].set(value)
                    continue
                elif info not in self._info_widget:
                    logging.debug('Skipping info "%s": "%s"', info, value)
                    continue
                
                label = self._info_widget[info]
                label.config(text = value if value else self.empty_info)
            logging.info("Set track info")
        except:
            errmsg = traceback.format_exc()
            logging.error(errmsg)
            messagebox.showerror(title = 'Speaker info...',
                                   message = 'Could not receive speaker information')

        #######################
        # Load queue
        #######################
        try:
            select = None
            if refresh_queue:
                logging.debug('Gettting queue from speaker')
                queue = speaker.get_queue()

                logging.debug('Deleting old items')
                self.__clear('queue')

                logging.debug('Inserting items (%d) to listbox', len(queue))
                for index, item in enumerate(queue):
                    string = self.label_queue.format(item.creator, item.title)
                    self.__queue_content.append(item)
                    self._queuebox.insert(tk.END, string)

            if playingTrack is not None:
                for index, item in enumerate(self.__queue_content):
                    if item.resources[0].uri == playingTrack:
                        self._queuebox.selection_clear(0, tk.END)
                        self._queuebox.selection_anchor(index)
                        self._queuebox.selection_set(index)
                        break
                
        except:
            errmsg = traceback.format_exc()
            logging.error(errmsg)
            messagebox.showerror(title = 'Queue...',
                                   message = 'Could not receive speaker queue')
                

    def __set_album_art(self, url, track_uri = None):
        if ImageTk is None:
            logging.warning('python-imaging-tk lib missing, skipping album art')
            return

        if not url:
            logging.warning('url is empty, returnning')
            return

        connection = None
        newImage = None
        
        # Receive Album art, resize it and show it
        try:

            raw_data = None
            
            if raw_data is None:
                logging.info('Could not find cached album art, loading from URL')
                resp = requests.get(url)
                raw_data = resp.content

            image = Image.open(BytesIO(raw_data))
            widgetConfig = self._info_widget['album_art'].config()
            thumbSize = (int(widgetConfig['width'][4]),
                         int(widgetConfig['height'][4]))

            logging.debug('Resizing album art to: %s', thumbSize)
            image.thumbnail(thumbSize,
                            Image.ANTIALIAS)
            newImage = ImageTk.PhotoImage(image = image)
            self._info_widget['album_art'].config(image = newImage)
        except:
            logging.error('Could not set album art, skipping...')
            logging.error(url)
            logging.error(traceback.format_exc())
        finally:
            if connection: connection.close()
            
            if self.__last_image: del self.__last_image
            self.__last_image = newImage

    def _update_buttons(self):
        logging.debug('Updating control buttons')
        speaker = self.__get_selected_speaker()
        
        newState = tk.ACTIVE if speaker else tk.DISABLED
        for button in self._control_buttons.values():
            button.config(state = newState)
        
    def _create_buttons(self):
        logging.debug('Creating buttons')
        buttonIndex = 0
        buttonWidth = 2
        
        button_prev = tk.Button(self._left,
                                width = buttonWidth,
                                command = self.__previous,
                                text = '<<')
        button_prev.grid(row = 1,
                         column = buttonIndex,
                         padx = 5,
                         pady = 5,
                         sticky = 'w')
        self._control_buttons['previous'] = button_prev
        buttonIndex += 1

        button_pause = tk.Button(self._left,
                                 width = buttonWidth,
                                 command = self.__pause,
                                 text = '||')
        button_pause.grid(row = 1,
                          column = buttonIndex,
                          padx = 5,
                          pady = 5,
                          sticky = 'w')
        self._control_buttons['pause'] = button_pause
        buttonIndex += 1

        button_play = tk.Button(self._left,
                                 width = buttonWidth,
                                 command = self.__play,
                                 text = '>')
        button_play.grid(row = 1,
                         column = buttonIndex,
                         padx = 5,
                         pady = 5,
                         sticky = 'w')
        self._control_buttons['play'] = button_play
        buttonIndex += 1

        button_next = tk.Button(self._left,
                                width = buttonWidth,
                                command = self.__next,
                                text = '>>')
        button_next.grid(row = 1,
                         column = buttonIndex,
                         padx = 5,
                         pady = 5,
                         sticky = 'w')
        self._control_buttons['next'] = button_next
        buttonIndex += 1

    def _create_menu(self):
        logging.debug('Creating menu')
        self._menubar = tk.Menu(self)
        self.__parent.config(menu = self._menubar)
        
        # File menu
        self._filemenu = tk.Menu(self._menubar, tearoff=0)
        self._menubar.add_cascade(label="File", menu=self._filemenu)

        self._filemenu.add_command(label="Scan for speakers",
                                   command=self.scan_speakers)
        
        self._filemenu.add_command(label="Exit",
                                   command=self._clean_exit)

        # Playback menu
        self._playbackmenu = tk.Menu(self._menubar, tearoff=0)
        self._menubar.add_cascade(label="Playback", menu=self._playbackmenu)

        self._playbackmenu.add_command(label = "Play",
                                       command = self.__play)
        
        self._playbackmenu.add_command(label = "Pause",
                                       command = self.__pause)
        
        self._playbackmenu.add_command(label = "Previous",
                                       command = self.__previous)
        
        self._playbackmenu.add_command(label = "Next",
                                       command = self.__next)


    def _play_selected_queue_item(self, evt):
        try:
            track, track_index = self.__get_selected_queue_item()
            speaker = self.__get_selected_speaker()

            if speaker is None or\
               track_index is None:
                logging.warning('Could not get track or speaker (%s, %s)', track_index, speaker)
                return
            
            speaker.play_from_queue(track_index)
            self.show_speaker_info(speaker, refresh_queue = False)
        except:
            logging.error('Could not play queue item')
            logging.error(traceback.format_exc())
            messagebox.showerror(title = 'Queue...',
                                   message = 'Error playing queue item, please check error log for description')
        

    def __previous(self):
        speaker = self.__get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.previous()
        self.show_speaker_info(speaker, refresh_queue = False)
        
    def __next(self):
        speaker = self.__get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.next()
        self.show_speaker_info(speaker, refresh_queue = False)

    def __pause(self):
        speaker = self.__get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.pause()
        self.show_speaker_info(speaker, refresh_queue = False)

    def __play(self):
        speaker = self.__get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.play()
        self.show_speaker_info(speaker, refresh_queue = False)

    def _load_settings(self):
        # Connect to database
        dbPath = os.path.join(USER_DATA, 'SoCo-Tk.sqlite')

        createStructure = False
        if not os.path.exists(dbPath):
            logging.info('Database "%s" not found, creating', dbPath)
            createStructure = True

            if not os.path.exists(USER_DATA):
                logging.info('Creating directory structure')
                os.makedirs(USER_DATA)

        logging.info('Connecting: %s', dbPath)
        self._connection = sql.connect(dbPath)
        self._connection.row_factory = sql.Row

        if createStructure:
            self._create_settings_database()

        # Load window geometry
        geometry = self.__get_config('window_geometry')
        if geometry:
            try:
                logging.info('Found geometry "%s", applying', geometry)
                self.__parent.geometry(geometry)
            except:
                logging.error('Could not set window geometry')
                logging.error(traceback.format_exc())


        message = 'Do you want to scan for speakers?'
        
        doscan = messagebox.askyesno(title = 'Scan...',
                                       message = message)
        if doscan: self.scan_speakers()

        # Load last selected speaker
        selected_speaker_uid = self.__get_config('last_selected')
        logging.debug('Last selected speaker: %s', selected_speaker_uid)

        selectIndex = None
        selectSpeaker = None
        for index, speaker in enumerate(self.__list_content):
            if speaker.speaker_info['uid'] == selected_speaker_uid:
                selectIndex = index
                selectSpeaker = speaker
                break

        if selectIndex is not None:
            self._listbox.selection_anchor(selectIndex)
            self._listbox.selection_set(selectIndex)
            self._listbox.see(selectIndex)
            self.show_speaker_info(speaker)      

    def __set_config(self, settingName, value):
        assert settingName is not None

        __sql = 'INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)'

        self._connection.execute(__sql, (settingName, value)).close()
        self._connection.commit()
        
    def __get_config(self, settingName):
        assert settingName is not None

        __sql = 'SELECT value FROM config WHERE name = ? LIMIT 1'

        with clib.closing(self._connection.execute(__sql, (settingName, ))) as cur:
            row = cur.fetchone()

            if not row:
                return None
            
            return row['value']

    def _create_settings_database(self):
        logging.debug('Creating tables')
        self._connection.executescript('''
            CREATE TABLE IF NOT EXISTS config(
                config_id   INTEGER,
                name        TEXT UNIQUE,
                value       TEXT,
                PRIMARY KEY(config_id)
            );
                
            CREATE TABLE IF NOT EXISTS speakers(
                speaker_id  INTEGER,
                name        TEXT,
                ip          TEXT,
                uid         TEXT,
                serial      TEXT,
                mac         TEXT,
                PRIMARY KEY(speaker_id)
            );
                
            CREATE TABLE IF NOT EXISTS images(
                image_id        INTEGER,
                uri             TEXT UNIQUE,
                image           BLOB,
                PRIMARY KEY(image_id)
            );
        ''').close()

        logging.debug('Creating index')
        self._connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_image_uri ON images(uri)
        ''').close()

        self._connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_config_name ON config(name)
        ''').close()

def main(root):
    logging.debug('Main')
    sonosList = SonosList(root)
    sonosList.mainloop()
    sonosList.destroy()

if __name__ == '__main__':
    logging.info('Using data dir: "%s"', USER_DATA)
    
    root = tk.Tk()
    try:
        root.wm_title('SoCo')
        root.minsize(800,400)
        main(root)
##    except:
##        logging.debug(traceback.format_exc())
    finally:
        root.quit()
        root.destroy()
