#!/usr/bin/env python

import contextlib as clib
import logging
import tkinter as tk
import traceback
import platform
import os
import sqlite3 as sql
from io import BytesIO

from utils import parse_time
import requests
from tkinter import messagebox

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

logging.basicConfig(format='%(asctime)s %(levelname)10s: %(message)s', level = logging.INFO)

USER_DATA = None

if platform.system() == 'Windows':
    USER_DATA = os.path.join(os.getenv('APPDATA'), 'SoCo-Tk')
elif platform.system() == 'Linux':
    USER_DATA = './data/'



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

        self.__parent.protocol('WM_DELETE_WINDOW', self.clean_exit)
        
        self.grid(row = 0,
                  column = 0,
                  ipadx = 5,
                  ipady = 5,
                  sticky = 'news')

        self.__list_content = []
        self.__queue_content = []

        self._control_buttons = {}
        self.now_playing_widget = {}

        self.__last_selected = None
        self.__current_speaker = None
        self._connection = None

        self.empty_info = '-'
        self.label_queue = '{} - {}'

        self.create_widgets()
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
        speakers = soco.discover()
        if not speakers:
            return logging.debug("No speakers found")
        speakers = list(speakers)
        logging.debug('Found %d speaker(s)', len(speakers))
        [s.get_speaker_info() for s in speakers]
        self.add_speakers(speakers)

    def clean_exit(self):
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
            

    def add_speakers(self, speakers):
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
        
    def create_widgets(self):
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

        self.create_now_playing_widgets()

    def create_now_playing_widgets(self):
        info_index = 0

        label = tk.Label(self._info, text = 'Now Playing....')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')

        info_index += 1

        ###################################
        # Title
        ###################################
        label = tk.Label(self._info, text = 'Title:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['title'] = tk.Label(self._info,
                                             text=self.empty_info,
                                             anchor='w')
        
        self.now_playing_widget['title'].grid(row=info_index,
                                       column=1,
                                       padx=5,
                                       pady=5,
                                       sticky='we')
        info_index += 1

        ###################################
        # Artist
        ###################################
        label = tk.Label(self._info, text = 'Artist:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['artist'] = tk.Label(self._info,
                                             text = self.empty_info,
                                             anchor = 'w')
        
        self.now_playing_widget['artist'].grid(row = info_index,
                                        column = 1,
                                        padx = 5,
                                        pady = 5,
                                        sticky = 'we')
        info_index += 1

        ###################################
        # Album
        ###################################
        label = tk.Label(self._info, text = 'Album:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['album'] = tk.Label(self._info,
                                             text = self.empty_info,
                                             anchor = 'w')
        
        self.now_playing_widget['album'].grid(row = info_index,
                                       column = 1,
                                       padx = 5,
                                       pady = 5,
                                       sticky = 'we')
        info_index += 1

        ###################################
        # Volume
        ###################################
        label = tk.Label(self._info, text = 'Volume:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['volume'] = tk.Scale(self._info,
                                              from_ = 0,
                                              to = 100,
                                              tickinterval = 10,
                                              orient = tk.HORIZONTAL)
        
        self.now_playing_widget['volume'].grid(row = info_index,
                                        column = 1,
                                        padx = 5,
                                        pady = 5,
                                        sticky = 'we')

        self.now_playing_widget['volume'].bind(
            '<ButtonRelease-1>', self.volume_changed_event)

        info_index += 1

        ###################################
        # Duration
        ###################################

        label = tk.Label(self._info, text = 'Position:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['position'] = tk.Label(self._info,
                                             text=self.empty_info,
                                             anchor='w')
        
        self.now_playing_widget['position'].grid(row=info_index,
                                       column=1,
                                       padx=5,
                                       pady=5,
                                       sticky='we')
        info_index += 1

        label = tk.Label(self._info, text = 'Duration:')
        label.grid(row = info_index,
                   column = 0,
                   sticky = 'w')
        
        self.now_playing_widget['duration'] = tk.Label(self._info,
                                             text=self.empty_info,
                                             anchor='w')
        
        self.now_playing_widget['duration'].grid(row=info_index,
                                       column=1,
                                       padx=5,
                                       pady=5,
                                       sticky='we')
        info_index += 1

        self.now_playing_widget['volume'].bind(
            '<ButtonRelease-1>', self.volume_changed_event)

        info_index += 1



        ###################################
        # Album art
        ###################################
        self.now_playing_widget['album_art'] = tk.Label(self._info,
                                                 image = tk.PhotoImage(),
                                                 width = 150,
                                                 height = 150)
        
        self.now_playing_widget['album_art'].grid(row = info_index,
                                           column = 1,
                                           padx = 5,
                                           pady = 5,
                                           sticky = 'nw')

    def get_selected_speaker(self):
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

    def get_selected_queue_item(self):
        widget = self._queuebox

        selection = widget.curselection()
        if not selection:
            return None, None

        index = int(selection[0])

        assert len(self.__queue_content) > index
        track = self.__queue_content[index]

        return track, index
        
    def volume_changed_event(self, evt):
        if not self.__current_speaker:
            logging.warning('No speaker selected')
            return
        
        speaker = self.__current_speaker
        volume = self.now_playing_widget['volume'].get()

        logging.debug('Changing volume to: %d', volume)
        speaker.volume(volume)

    def clear(self, type_name):
        if type_name == 'queue':
            logging.debug('Deleting old items')
            self._queuebox.delete(0, tk.END)
            del self.__queue_content[:]
            self.__queue_content = []
        elif type_name == 'album_art':
            self.now_playing_widget[type_name].config(image = None)
        
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

    def set_now_playing_info(self, track, speaker):
        BASIC_DATA = ("title", "artist", "album")
        playing_track = track['uri']
        track['volume'] = speaker.volume

        for key in BASIC_DATA:
            label = self.now_playing_widget[key]
            text = track.get(key) if track.get(key) else self.empty_info
            label.config(text=text)

        self.clear('album_art')

        art = track.get("album_art")
        if art:
            self.set_album_art(art, track_uri=playing_track)

        volume = track.get("volume")
        if volume:
            self.now_playing_widget["volume"].set(volume)

        duration = track.get("duration", "0:00:0")
        position = track.get("position", "0:00:0")
        duration = parse_time(duration)
        position = parse_time(position)
        self.now_playing_widget["duration"].config(text=duration)
        self.now_playing_widget["position"].config(text=position)

        logging.info("Set track info")
        

    def show_speaker_info(self, speaker, refresh_queue=None):
        refresh_queue = True
        if speaker is not None and (
            not isinstance(speaker, soco.SoCo)):
            raise TypeError('Unsupported type: %s', type(speaker))

        self.__current_speaker = speaker
        
        new_state = tk.ACTIVE if speaker is not None else tk.DISABLED
        self.now_playing_widget['volume'].config(state=new_state)
        
        if speaker is None:
            for info in self.now_playing_widget.keys():
                if info == 'volume':
                    self.now_playing_widget[info].set(0)
                    continue
                elif info == 'album_art':
                    self.clear(info)
                    continue
                
                self.now_playing_widget[info].config(text=self.empty_info)
            logging.info("Removed track info")
            return

        #######################
        # Load speaker info
        #######################
        playing_track = None
        try:
            logging.info('Receive speaker info from: "%s"' % speaker)
            track = speaker.get_current_track_info()
            self.set_now_playing_info(track, speaker)
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
                self.clear('queue')

                logging.debug('Inserting items (%d) to listbox', len(queue))
                for index, item in enumerate(queue):
                    string = self.label_queue.format(item.creator, item.title)
                    self.__queue_content.append(item)
                    self._queuebox.insert(tk.END, string)

            if playing_track is not None:
                for index, item in enumerate(self.__queue_content):
                    if item.resources[0].uri == playing_track:
                        self._queuebox.selection_clear(0, tk.END)
                        self._queuebox.selection_anchor(index)
                        self._queuebox.selection_set(index)
                        break
                
        except:
            errmsg = traceback.format_exc()
            logging.error(errmsg)
            messagebox.showerror(title = 'Queue...',
                                   message = 'Could not receive speaker queue')


    def get_album_art_from_database(self, track_uri):
        if not self._connection:
            logging.error("No database connection to get art from.")
            return None
        elif not track_uri:
            logging.error("No URI to query.")
            return None
        c = self._connection.cursor()
        c.execute("SELECT * FROM images where uri=?", (track_uri,))
        top_res = c.fetchone()
        if top_res:
            return top_res[1]
        return None

    def set_album_art_in_database(self, track_uri, data):
        if not self._connection:
            logging.error("No database connection to get art from.")
            return None
        elif not track_uri or not data:
            logging.error("No URI or data to insert.")
            return None
        c = self._connection.cursor()
        c.execute("INSERT INTO images VALUES (?, ?)",(track_uri, data))

                

    def set_album_art(self, url, track_uri=None):
        if ImageTk is None:
            logging.warning('python-imaging-tk lib missing, skipping album art')
            return

        if not url:
            logging.warning('url is empty, returning')
            return
        
        # Receive Album art, resize it and show it
        try:

            raw_data = self.get_album_art_from_database(track_uri)

            if raw_data is None:
                logging.info('Could not find cached album art, loading from URL')
                resp = requests.get(url)
                raw_data = resp.content
                self.set_album_art_in_database(track_uri, raw_data)

            image = Image.open(BytesIO(raw_data))
            widgetConfig = self.now_playing_widget['album_art'].config()
            thumbSize = (int(widgetConfig['width'][4]),
                         int(widgetConfig['height'][4]))

            logging.debug('Resizing album art to: %s', thumbSize)
            image.thumbnail(thumbSize,
                            Image.ANTIALIAS)
            new_image = ImageTk.PhotoImage(image = image)
            self.now_playing_widget['album_art'].config(image=new_image)
        except:
            logging.error('Could not set album art, skipping...')
            logging.error(url)
            logging.error(traceback.format_exc())

    def _update_buttons(self):
        logging.debug('Updating control buttons')
        speaker = self.get_selected_speaker()
        
        new_state = tk.ACTIVE if speaker else tk.DISABLED
        for button in self._control_buttons.values():
            button.config(state = new_state)
        
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
                                   command=self.clean_exit)

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
            track, track_index = self.get_selected_queue_item()
            speaker = self.get_selected_speaker()

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
        speaker = self.get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.previous()
        self.show_speaker_info(speaker, refresh_queue = False)
        
    def __next(self):
        speaker = self.get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.next()
        self.show_speaker_info(speaker, refresh_queue = False)

    def __pause(self):
        speaker = self.get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.pause()
        self.show_speaker_info(speaker, refresh_queue = False)

    def __play(self):
        speaker = self.get_selected_speaker()
        if not speaker:
            raise SystemError('No speaker selected, this should not happend')

        speaker.play()
        self.show_speaker_info(speaker, refresh_queue = False)

    def _load_settings(self):
        # Connect to database
        self.dbPath = os.path.join(USER_DATA, 'SoCo-Tk.sqlite')

        create_structure = False
        if not os.path.exists(self.dbPath):
            logging.info('Database "%s" not found, creating', self.dbPath)
            create_structure = True

            if not os.path.exists(USER_DATA):
                logging.info('Creating directory structure')
                os.makedirs(USER_DATA)

        logging.info('Connecting: %s', self.dbPath)
        self._connection = sql.connect(self.dbPath)
        self._connection.row_factory = sql.Row

        if create_structure:
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

    def __set_config(self, setting_name, value):
        assert setting_name is not None

        __sql = 'INSERT OR REPLACE INTO config (name, value) VALUES (?, ?)'

        self._connection.execute(__sql, (setting_name, value)).close()
        self._connection.commit()
        
    def __get_config(self, setting_name):
        assert setting_name is not None

        __sql = 'SELECT value FROM config WHERE name = ? LIMIT 1'

        with clib.closing(self._connection.execute(__sql, (setting_name, ))) as cur:
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
                uri             TEXT UNIQUE,
                image           BLOB,
                PRIMARY KEY(uri)
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
